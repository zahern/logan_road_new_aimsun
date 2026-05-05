        subroutine kspcost_update(itmp)
c --
c -- This subroutine is to sort the available k shortest paths
c -- based on the current travel time.
c --
c -- This subroutine is called from loop.
c -- This subroutine does not call any other subroutines.
c --
c -- INPUT:
c -- itmp: the current destination
c -- OUTPUT:
c -- set of k shortest paths.
c --
      use muc_mod
c --
       ides=itmp 

      do 1, IP=2,totalpriority(ltype,ioccup,ides)
         n1=pp(ltype,ioccup,ides,ip,1)
         k1=pp(ltype,ioccup,ides,ip,2)
         m1=pp(ltype,ioccup,ides,ip,3)
         it1=pp(ltype,ioccup,ides,ip,4)
         if(n1.gt.0.or.k1.gt.0.or.m1.gt.0.or.it1.gt.0)then
         n2=pathpointerout1(ltype,ioccup,ides,n1,it1,k1,m1)
         k2=pathpointerout2(ltype,ioccup,ides,n1,it1,k1,m1)
         m2=pathpointerout3(ltype,ioccup,ides,n1,it1,k1,m1)
         it2=pathpointerout4(ltype,ioccup,ides,n1,it1,k1,m1)
	   if(n2.gt.0.and.k2.gt.0.and.m2.gt.0.and.it2.gt.0)then

         Arc=BackPointr(n2)+m2-1

              NextPenalty=penalty(arc,m1)
              NextDistance=TTimeOfBackLink(Arc)
 
              NArrivalTime=((NextDistance+NextPenalty)/
     *          TimeInterval)+it1+1
         if(NArrivalTime.ge.Iti_nu) NArrivalTime=Iti_nu

         labeloutCost(ltype,ioccup,ides,n1,it1,k1,m1)
     *   =labeloutCost(ltype,ioccup,ides,n2,NArrivalTime,k2,m2)+
     *        NextDistance+NextPenalty+cost(Arc,ltype,ioccup)

    
	   endif
	   endif
     
1      continue
      
c --     resort_the_kpath_arrays, as parallel as you can get.

      do 100, nn=1,noofnodes
         nt = nn   !G
         if (labeloutCost(ltype,ioccup,ides,nt,1,1,1).LT.Infinity) then
         m_k=Backpointr(nt+1)-backpointr(nt)+1

	    if( m_k .gt.MaxMove) then
		m_k = MaxMove 
		! Reason 1: Only centriod will satisfy this condition:IM .gt.MaxMove  
		! Reason 2: node nt is the corresponding node (the same node) for destination ides 
		! Reason 3: labeloutCost() on the centriod are zero (the same) for all the movements for all the time
	    endif
! End of modification


         do 205 m=1,m_k         
         do 205 it=1,Iti_nu         
         k=1
         do 111, while (k.lt.kpaths)
            k0=labelpointerout(ltype,ioccup,ides,nt,it,k,m)
            k1=labelpointerout(ltype,ioccup,ides,nt,it,k+1,m)
          if(k0.lt.1) k0=1
          if(k1.lt.1) k1=1
         if (labeloutCost(ltype,ioccup,ides,nt,it,k0,m).gt.
     *         labeloutCost(ltype,ioccup,ides,nt,it,k1,m)) then
               labelpointerout(ltype,ioccup,ides,nt,it,k+1,m)=k0
               labelpointerout(ltype,ioccup,ides,nt,it,k,m)=k1
               if (k.eq.1) then
                  k=k+1
               else
                  k=k-1
               endif
            else
               k=k+1
            endif
111      continue
205      continue
         endif
100   continue
      return
      end
