      subroutine RT_GET_VEH_OPAC(i,nu,pha2,nodenumber)
c	  ,nu_ph2,narcs,contveh_que)
c     + icurrnt,nu_ve	  )
c --    Output:
c --    vehicle in link (2,:,:) and queue (1,:,:) per phase : contveh_que(:,phase,link)

      use LinkList_mod
      use muc_mod
      use vector_mod
      use Intooi_mod

      integer Itp1,j,lnum,mg,nll,inode,pha2,nu_ph2,narcs,k,i,m,nu
      integer nodenumber
c             integer nu_ve
      logical Itp2
c      integer contveh_que(2,nu_ph1,narcs)
c             ingeter	  icurrnt(nu_ve)	  
C      integer contveh_que(2,nu_ph1,narcs)	  
c      integer,allocatable::movement(:,:,:)	  
c      integer error
c     allocate (contveh(n2-n1+1),stat=error)
c 	if(error.ne.0) print *,'error'
c	contveh(:)=0
c      print *,'Alex170',pha2,i,contveh_que(2,1,1)
      contveh_que(1,pha2,i)=0
      contveh_que(2,pha2,i)=0
      j=0	  
c			 print *,'Alex180',i
c			 print *,'Alex180',npar(i)

c      if(npar(i).gt.0)then 
c	  if(npar(i).gt.MaxLinkVeh)then
c	  print *, 'error' 
c	  endif

c -- loop over all vehicles on the link
c      print *,'Alex190'	

      p_mtxj_value=>LinkVehList(i)

! -- This do while loop is to go through all the vehicle in the LinkVehList(i)

      do while(associated(p_mtxj_value%next_veh)) 
C	if(iteration.gt.0)
      j=p_mtxj_value%veh
c      print *, 'Alex000',j 
       if(j.gt.0)then
c    	icu=i
      Itp1=icurrnt(j)+1
      Itp2=.False.
      inode=nint(VhcAtt_Value(j,Itp1,1))
c	if(j.eq.42)then
c	if(iteration.gt.0.and.j.eq.213)print *,'Alex221-j=',j,inode,i,Itp1
c	endif
c      print *, 'Alex001' 
        do k=backpointr(inode),backpointr(inode+1)-1
c	if(iteration.gt.0.and.j.eq.213)print *,
c     +  'Alex222',idnod(i),UNodeOfBackLink(k),k
c      print *, 'Alex002' 
      	  if(idnod(i).eq.UNodeOfBackLink(k))then
            nll=BackToForLink(k)
            Itp2=.True.
            exit
      	  endif
		
        enddo
c      print *, 'Alex003' 
c-- nll is the next link, in reality this information needs to be estimated . . .

             do 2222 m=6,5+nsign(nu,5)
		        lnum=nsign(nu,m)
		        do 2222 mg=1,llink(lnum,nu_mv+1)

c      if(nodenumber.eq.120)then
c        print *,'j=',j,'nll=',nll,'lnum=',lnum,'i=',i,
c     +	   movement(lnum,pha2,mg),llink(i,mg)
c        pause
c      endif	  
				
                 if((movement(lnum,pha2,mg).eq.1).and.
     +			   ((lnum.eq.i).and.(llink(i,mg).eq.nll)))then

	               contveh_que(2,pha2,i)=contveh_que(2,pha2,i)+1
				   
                   if(xpar(j).le.0.0001)then
			         contveh_que(1,pha2,i)=contveh_que(1,pha2,i)+1
                   endif
				   
                  exit
				  
                 endif

2222			continue
c      print *, 'Alex004' 
c		 endif
c      print *, 'Alex0041111' 	  

       endif
	   
       p_mtxj_value=>p_mtxj_value%next_veh
		
       enddo  ! end do while
c	endif
c      print *, 'Alex005' 
c	deallocate (contveh_que,stat=error)
      return
      end
  