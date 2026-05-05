        subroutine kspcost_priorities
c --
c -- This porgram is a preprocessing step before the ksp_update
c -- subroutine.
c --
c -- This subroutine is called from ksp_main.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT: 
c --   no specific input.
c -- OUTPUT:
c --   no specific output.
c --  
 
      use muc_mod
c --
c -- Priority() is to keep the pririority for every node-path-move combination
c --
c -- pp() is a PointerToPriority(D,P) array, that identifies the
c -- node-path-movement combination that corresponds to the priority
c -- number P for the destination D
c --
      totalprior=1
c      do 1, m=1,nu_mv
      do 1, m=1,MaxMove
         do 1, k=1,kpaths
            do 1, nq=1,noofnodes
            do 1, iiss=1,no_link_type
            do 1, jjss=1,no_occupancy_level
            do 1, itime=1,Iti_nu
               priority(iiss,jjss,ides,nq,itime,k,m)=0
1          continue

c       Do 10, M=1,nu_mv
       Do 10, M=1,MaxMove
            do 10, itime=1,Iti_nu
          	 do 10, k=1,kpaths
         Priority(ltype,ioccup,Ides,Destination(ides),itime,k,M)=1
10     Continue

      do 97, nn=1,noofnodes

!	   if(connectivity(nn,ides).lt.1) go to 97
         nodee=nn   !G
         if(nodee.eq.destin) go to 97
         if (labelOutCost(ltype,ioccup,IDes,nodee,1,1,1).
     *               LT.Infinity) Then
            mxmv=BackPointr(nodee+1)-BackPointr(nodee)+1
          do 100,mov=1,mxmv
            do 100, kpath=1,kpaths
              do 100, Itime=1,Iti_nu
               k=kpath
               ny=nodee
               m=mov
               it=itime
               icount=0
               finish=.false.
               do 110, while (.not.finish)
               if (priority(ltype,ioccup,ides,ny,it,k,m).eq.0.and.
     *	     ny.ne.0.and.k.ne.0.and.m.ne.0.and.it.ne.0) then
                  icount=icount+1
                  Track(icount,1)=ny
                  Track(icount,2)=k
                  Track(icount,3)=m
                  Track(icount,4)=it
                  ktemp=k
                  mtemp=m
                  ntemp=ny
                  ittemp=it
                  ny=pathpointerout1(ltype,ioccup,
     *                      ides,ntemp,ittemp,ktemp,mtemp)
                  k=pathpointerout2(ltype,ioccup,
     *                      ides,ntemp,ittemp,ktemp,mtemp)
                  m=pathpointerout3(ltype,ioccup,
     *                      ides,ntemp,ittemp,ktemp,mtemp)
                  it=pathpointerout4(ltype,ioccup,
     *                      ides,ntemp,ittemp,ktemp,mtemp)
               else
109               finish=.true.
               endif
110         continue

            do 200, while (icount.gt.0)
               totalprior=totalprior+1
               priority(ltype,ioccup,ides,track(icount,1),
     *              track(icount,4),
     *              track(icount,2),
     *              track(icount,3))=totalprior
               pp(ltype,ioccup,ides,totalprior,1)=track(icount,1)
               pp(ltype,ioccup,ides,totalprior,2)=track(icount,2)
               pp(ltype,ioccup,ides,totalprior,3)=track(icount,3)
               pp(ltype,ioccup,ides,totalprior,4)=track(icount,4)
               icount=icount-1
200         continue
100      continue
          Endif
97     continue
         totalpriority(ltype,ioccup,ides)=totalprior
         return
         end
