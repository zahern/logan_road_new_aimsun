      	subroutine stop_control(nodenumber)
! --
! -- This subroutine calculates the green time for each approach if the
! -- intersection has stop control.
! --
! -- This subroutine is called from intersection_control.
! -- This subroutine does not call any other subroutines.
! --
! -- INPUT :
! -- nodenumber : the intersection number.
! --
! -- OUTPUT :
! --  green times for each approach and each movement.
! --
! --
      	use muc_mod
	  integer i1,i2,nodenumber
	  real g1
! --
! -- set the green for each approach and each movement according to the
! -- proportion of the queue length on the approach to the total queue
! -- length on all approaches.
! --
      i1=backpointr(nodenumber)
      i2=backpointr(nodenumber+1)-1
      do i=i1,i2
         ik=BackToForLink(i)
         total_count(ik) = 0
		 do j=i1,i2
	if (j.ne.i.and.vehicle_queue(j).gt.0) total_count(ik)=
     +  total_count(ik)+1
		 enddo
      enddo
! --
!      if(total_volume.lt.1) then
        do i=i1,i2
		  do j=1,llink(BackToForLink(i),nu_mv+1)
		    green(BackToForLink(i),j)=tii*60
		  enddo
        enddo

	return
    	end
